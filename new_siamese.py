import tensorflow as tf
import pandas as pd
import numpy as np


class Data(object):
    def __init__(self):
        self.train_x1 = None
        self.train_x2 = None
        self.train_labels = None
        self.valid_x1 = None
        self.valid_x2 = None
        self.valid_labels = None

    def import_data(self, train_csv):
        df = pd.read_csv(train_csv)
        return df

    def preprocess(self, df):
        import string
        vocab_chars = string.ascii_lowercase + '0123456789 '
        vocab2ix_dict = {char:(ix+1) for ix, char in enumerate(vocab_chars)}
        vocab_length = len(vocab_chars) + 1
        def sentence2onehot(sentence, vocab2ix_dict = vocab2ix_dict):
            # translate sentence string into indices
            sentence_ix = [vocab2ix_dict[x] for x in list(sentence) if x in vocab_chars]
            # Pad or crop to embedding dimension
            sentence_ix = (sentence_ix + [0]*self.embedding_dim)[0:self.embedding_dim]
            return(sentence_ix)
        self.train_x1 = np.matrix(df.question1.str.lower().apply(sentence2onehot).tolist())
        self.train_x2 = np.matrix(df.question2.str.lower().apply(sentence2onehot).tolist())
        self.train_labels = np.array(df.is_duplicate)

    def subsample(self, n_train_samples, n_validation_samples):
        train_size = self.train_x1.shape[0]
        global_idx = np.random.choice(train_size, n_train_samples + n_validation_samples, replace=False)
        np.random.shuffle(global_idx)
        train_sample_idx = global_idx[:n_train_samples]
        validation_sample_idx = global_idx[n_train_samples:]
        self.train_x1 = self.train_x1[train_sample_idx, :self.embedding_dim]
        self.train_x2 = self.train_x2[train_sample_idx, :self.embedding_dim]
        self.train_labels = self.train_labels[train_sample_idx]
        self.valid_x1 = self.train_x1[validation_sample_idx, :self.embedding_dim]
        self.valid_x2 = self.train_x2[validation_sample_idx, :self.embedding_dim]
        self.valid_labels = self.train_labels[validation_sample_idx]

    def batch_generator(self, batch_size):
            l = self.train_x1.shape[0]
            for ndx in range(0, l, batch_size):
                yield (self.train_x1[ndx:min(ndx + batch_size, l), :],
                       self.train_x2[ndx:min(ndx + batch_size, l), :],
                       self.train_labels[ndx:min(ndx + batch_size, l)],
                       self.valid_x1[ndx:min(ndx + batch_size, l), :],
                       self.valid_x2[ndx:min(ndx + batch_size, l), :],
                       self.valid_labels[ndx:min(ndx + batch_size, l)],
                       )
    def run(self, train_csv, n_train_samples=400000, n_validation_samples=10000, embedding_dim=80):
        df = self.import_data(train_csv)
        self.embedding_dim = embedding_dim
        self.preprocess(df)
        self.subsample(n_train_samples, n_validation_samples)



class Architecture(object):
    def __init__(self, data, graph):
        self.graph = graph
        self.data = data

    def stacked_biRNN(self, x, n_layers, lstm_size):
        embed = tf.nn.embedding_lookup(tf.diag(tf.ones(shape=[self.data.embedding_dim])), x)
        embed_split = tf.split(axis=1, num_or_size_splits=self.data.embedding_dim, value=embed)
        embed_split = [tf.squeeze(x, axis=[1]) for x in embed_split]
        fw_stack = tf.contrib.rnn.MultiRNNCell([tf.contrib.rnn.BasicLSTMCell(lstm_size, reuse=None) for _ in range(n_layers)])
        bw_stack = tf.contrib.rnn.MultiRNNCell([tf.contrib.rnn.BasicLSTMCell(lstm_size, reuse=None) for _ in range(n_layers)])
        outputs, _, _ = tf.contrib.rnn.static_bidirectional_rnn(fw_stack,
                                                                bw_stack,
                                                                embed_split,
                                                                dtype=tf.float32)
        final_state = outputs[-1]
        return final_state

    def biRNN(self, x, lstm_size):
        embed = tf.nn.embedding_lookup(tf.diag(tf.ones(shape=[self.data.embedding_dim])), x)
        embed_split = tf.split(axis=1, num_or_size_splits=self.data.embedding_dim, value=embed)
        embed_split = [tf.squeeze(x, axis=[1]) for x in embed_split]
        fw_cell_unit = tf.contrib.rnn.BasicLSTMCell#tf.nn.rnn_cell.BasicLSTMCell
        bw_cell_unit = tf.contrib.rnn.BasicLSTMCell#tf.nn.rnn_cell.BasicLSTMCell
        fw = fw_cell_unit(lstm_size, reuse=None)
        bw = bw_cell_unit(lstm_size, reuse=None)
        outputs, _, _ = tf.contrib.rnn.static_bidirectional_rnn(fw,
                                                                bw,
                                                                embed_split,
                                                                dtype=tf.float32)
        final_state = outputs[-1]
        return final_state

    def rnn(self, x, lstm_size):
        embed = tf.nn.embedding_lookup(tf.diag(tf.ones(shape=[self.data.embedding_dim])), x)
        embed_split = tf.split(axis=1, num_or_size_splits=self.data.embedding_dim, value=embed)
        embed_split = [tf.squeeze(x, axis=[1]) for x in embed_split]
        fw_cell_unit = tf.contrib.rnn.BasicLSTMCell#tf.nn.rnn_cell.BasicLSTMCell
        fw = fw_cell_unit(lstm_size, reuse=None)
        outputs, _, _ = tf.contrib.rnn.static_rnn(fw, embed_split, dtype=tf.float32)
        final_state = outputs[-1]
        return final_state
    
    def dense_unit(self, x, name, input_size, output_size):
            bn = tf.nn.batch_normalization(x, mean = 0.0, variance = 1.0, offset=tf.constant(0.0), scale=None, variance_epsilon=0.001)
            W1 = tf.get_variable(name="W"+name, shape=[input_size, output_size], initializer=tf.contrib.layers.xavier_initializer())
            b1 = tf.get_variable(name="b"+name, shape=[1], initializer=tf.random_normal_initializer(stddev=0.1))
            h1 = tf.nn.relu(tf.matmul(bn, W1) + b1)
            return h1

class Loss(object):

    def __init__(self, q1_repr, q2_repr, labels):
        self.q1_repr = q1_repr
        self.q2_repr = q2_repr
        self.labels = labels

    def contrastive_loss_l1(self, q1_repr, q2_repr, margin):
        labels_t = tf.to_float(self.labels)
        labels_f = tf.subtract(1.0, tf.to_float(self.labels), name="1-yi")          # labels_ = !labels;
        manhattan = tf.squeeze(tf.norm(self.q1_repr - self.q2_repr, ord=1, axis=1, keep_dims=True))
        C = tf.constant(margin, name="C")
        pos = tf.multiply(labels_t, manhattan, name="y_x_eucd")
        neg = tf.multiply(labels_f, tf.maximum(0.0, tf.subtract(C, manhattan)), name="Ny_C-eucd")
        losses = tf.add(pos, neg, name="losses")
        loss = 0.5*tf.reduce_mean(losses, name="loss")
        tf.summary.scalar('contrastive_loss', loss)
        return loss

class Optimization(object):
    def __init__(self, loss):
        self.loss = loss
        self.train_opt = None
    def adam(self, lr):
        self.train_opt = tf.train.AdamOptimizer(lr).minimize(self.loss)

class Run(object):
    def __init__(self, data):
        self.data = data
        self.x1 = tf.placeholder(dtype=tf.int32, shape=(None, data.embedding_dim), name='x1')
        self.x2 = tf.placeholder(dtype=tf.int32, shape=(None, data.embedding_dim), name='x2')
        self.labels = tf.placeholder(dtype=tf.int32, shape=(None,), name='labels')

    def create_feed_dict(self, x1, x2, labels):
        return {self.x1 : x1,
                self.x2 : x2,
                self.labels : labels}
